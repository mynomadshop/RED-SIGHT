<#
    Test-RedSightSetup.ps1

    Self-contained tests for the platform-independent parts of the RedSight
    setup pipeline. No Pester dependency, so this runs anywhere PowerShell does
    (including Linux CI), which is what makes it useful as a pre-build gate.

    Windows-only behaviour (DISM, Docker Desktop, MSI installs) is exercised by
    the build workflow's install test on a real Windows runner, not here.

        pwsh -File installer/tests/Test-RedSightSetup.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$scripts = Join-Path (Split-Path -Parent $scriptDir) 'scripts'
. (Join-Path $scripts 'RedSight-Preflight.ps1')

$script:Pass = 0
$script:Fail = 0
$script:Failures = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][AllowNull()]$Condition)
    if ($Condition) {
        $script:Pass++
        Write-Host "  PASS  $Name" -ForegroundColor Green
    } else {
        $script:Fail++
        $script:Failures.Add($Name)
        Write-Host "  FAIL  $Name" -ForegroundColor Red
    }
}

function Assert-Equal {
    param([Parameter(Mandatory)][string]$Name, [AllowNull()]$Expected, [AllowNull()]$Actual)
    $ok = ($null -eq $Expected -and $null -eq $Actual) -or
          ($null -ne $Expected -and $null -ne $Actual -and $Expected.ToString() -eq $Actual.ToString())
    if ($ok) {
        $script:Pass++
        Write-Host "  PASS  $Name" -ForegroundColor Green
    } else {
        $script:Fail++
        $script:Failures.Add("$Name (expected '$Expected', got '$Actual')")
        Write-Host "  FAIL  $Name -- expected '$Expected', got '$Actual'" -ForegroundColor Red
    }
}

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("rs-test-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

try {

# ==========================================================================
Write-Host "`n== ConvertTo-RsVersion ==" -ForegroundColor Cyan
# ==========================================================================

Assert-Equal -Name 'parses a plain python version'      -Expected '3.12.10' -Actual (ConvertTo-RsVersion -Text '3.12.10')
Assert-Equal -Name 'parses python banner output'        -Expected '3.12.10' -Actual (ConvertTo-RsVersion -Text 'Python 3.12.10')
Assert-Equal -Name 'parses a docker version banner'     -Expected '27.4.0'  -Actual (ConvertTo-RsVersion -Text 'Docker version 27.4.0, build bde2b89')
Assert-Equal -Name 'parses a node v-prefixed version'   -Expected '22.14.0' -Actual (ConvertTo-RsVersion -Text 'v22.14.0')
Assert-Equal -Name 'parses a two-component version'     -Expected '3.13'    -Actual (ConvertTo-RsVersion -Text 'Python 3.13')
Assert-True  -Name 'returns null for non-version text'  -Condition ($null -eq (ConvertTo-RsVersion -Text 'no digits here'))
Assert-True  -Name 'returns null for empty input'       -Condition ($null -eq (ConvertTo-RsVersion -Text ''))

# ==========================================================================
Write-Host "`n== Test-RsVersionInRange ==" -ForegroundColor Cyan
# ==========================================================================

$min = [version]'3.12.0'
$max = [version]'3.14.0'
Assert-True -Name '3.12.0 is in [3.12, 3.14)'      -Condition (Test-RsVersionInRange -Version ([version]'3.12.0') -Minimum $min -ExclusiveMaximum $max)
Assert-True -Name '3.12.10 is in range'            -Condition (Test-RsVersionInRange -Version ([version]'3.12.10') -Minimum $min -ExclusiveMaximum $max)
Assert-True -Name '3.13.2 is in range'             -Condition (Test-RsVersionInRange -Version ([version]'3.13.2') -Minimum $min -ExclusiveMaximum $max)
Assert-True -Name '3.11.9 is rejected (too old)'   -Condition (-not (Test-RsVersionInRange -Version ([version]'3.11.9') -Minimum $min -ExclusiveMaximum $max))
Assert-True -Name '3.14.0 is rejected (upper excl)' -Condition (-not (Test-RsVersionInRange -Version ([version]'3.14.0') -Minimum $min -ExclusiveMaximum $max))
Assert-True -Name 'null version is rejected'       -Condition (-not (Test-RsVersionInRange -Version $null -Minimum $min -ExclusiveMaximum $max))
Assert-True -Name 'no upper bound accepts 99.0'    -Condition (Test-RsVersionInRange -Version ([version]'99.0') -Minimum $min -ExclusiveMaximum $null)

# ==========================================================================
Write-Host "`n== Repair-RsHardcodedPaths ==" -ForegroundColor Cyan
# ==========================================================================

# Build a fake install tree containing the author-machine path in all three
# encodings that appear in the shipped RedSight payload.
$proj = Join-Path $tmpRoot 'RedSightInstall'
New-Item -ItemType Directory -Path $proj -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $proj '.venv-ui') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $proj 'scripts') -Force | Out-Null

# plain backslash form, as in LAUNCH-REDSIGHT-DESKTOP.ps1
Set-Content -LiteralPath (Join-Path $proj 'launcher.ps1') -NoNewline -Encoding utf8 `
    -Value '$R=''C:\Users\walim\RedSight''; & (Join-Path $R ''RESTART-REDSIGHT.ps1'')'
# python raw string, as in launch_redsight_command_center.py
Set-Content -LiteralPath (Join-Path $proj 'launcher.py') -NoNewline -Encoding utf8 `
    -Value 'ROOT = r"C:\Users\walim\RedSight"'
# JSON-escaped form - the case the previous bootstrap could not match
Set-Content -LiteralPath (Join-Path $proj 'config.json') -NoNewline -Encoding utf8 `
    -Value '{"root": "C:\\Users\\walim\\RedSight", "log": "C:\\Users\\walim\\RedSight\\logs"}'
# forward-slash form
Set-Content -LiteralPath (Join-Path $proj 'settings.yml') -NoNewline -Encoding utf8 `
    -Value 'root: C:/Users/walim/RedSight'
# a deeper path that must keep its trailing segments
Set-Content -LiteralPath (Join-Path $proj 'scripts\deep.py') -NoNewline -Encoding utf8 `
    -Value 'P = r"C:\Users\walim\RedSight\.venv-ui\Scripts\python.exe"'
# a file that must be left completely alone
Set-Content -LiteralPath (Join-Path $proj 'untouched.py') -NoNewline -Encoding utf8 `
    -Value 'X = "nothing to see here"'
# a file inside an excluded directory
Set-Content -LiteralPath (Join-Path $proj '.venv-ui\excluded.py') -NoNewline -Encoding utf8 `
    -Value 'ROOT = r"C:\Users\walim\RedSight"'

$result = Repair-RsHardcodedPaths -ProjectRoot $proj
$sep = [System.IO.Path]::DirectorySeparatorChar
$expected = (Resolve-Path -LiteralPath $proj).Path.TrimEnd('\')
$expectedEsc = $expected -replace '\\', '\\'
$expectedFwd = $expected -replace '\\', '/'

Assert-Equal -Name 'rewrote exactly the five affected files' -Expected 5 -Actual $result.Rewritten
Assert-Equal -Name 'no rewrite failures'                     -Expected 0 -Actual $result.Failed

$launcher = Get-Content -LiteralPath (Join-Path $proj 'launcher.ps1') -Raw
Assert-True -Name 'plain path replaced in launcher.ps1'  -Condition ($launcher -like "*$expected*")
Assert-True -Name 'author path gone from launcher.ps1'   -Condition ($launcher -notlike '*walim*')

$py = Get-Content -LiteralPath (Join-Path $proj 'launcher.py') -Raw
Assert-True -Name 'python raw string rewritten'          -Condition ($py -notlike '*walim*')

$json = Get-Content -LiteralPath (Join-Path $proj 'config.json') -Raw
Assert-True -Name 'JSON-escaped path rewritten'          -Condition ($json -notlike '*walim*')
Assert-True -Name 'JSON stays escaped after rewrite'     -Condition ($json -like "*$expectedEsc*")
$jsonValid = $false
try { $null = $json | ConvertFrom-Json; $jsonValid = $true } catch { $jsonValid = $false }
Assert-True -Name 'JSON is still valid JSON'             -Condition $jsonValid

$yml = Get-Content -LiteralPath (Join-Path $proj 'settings.yml') -Raw
Assert-True -Name 'forward-slash path rewritten'         -Condition ($yml -notlike '*walim*')
Assert-True -Name 'forward-slash form preserved'         -Condition ($yml -like "*$expectedFwd*")

$deep = Get-Content -LiteralPath (Join-Path $proj 'scripts\deep.py') -Raw
Assert-True -Name 'trailing segments preserved on a deep path' `
            -Condition ($deep -like '*.venv-ui*Scripts*python.exe*' -and $deep -notlike '*walim*')

$untouched = Get-Content -LiteralPath (Join-Path $proj 'untouched.py') -Raw
Assert-Equal -Name 'unrelated file untouched' -Expected 'X = "nothing to see here"' -Actual $untouched

$excluded = Get-Content -LiteralPath (Join-Path $proj '.venv-ui\excluded.py') -Raw
Assert-True -Name 'files inside .venv-ui are excluded' -Condition ($excluded -like '*walim*')

# Idempotency: a second pass must find nothing left to do.
$again = Repair-RsHardcodedPaths -ProjectRoot $proj
Assert-Equal -Name 'second pass rewrites nothing (idempotent)' -Expected 0 -Actual $again.Rewritten

# ==========================================================================
Write-Host "`n== New-RsEnvFile ==" -ForegroundColor Cyan
# ==========================================================================

$envProj = Join-Path $tmpRoot 'EnvProj'
New-Item -ItemType Directory -Path $envProj -Force | Out-Null
Assert-True -Name 'no .env created without .env.example' -Condition (-not (New-RsEnvFile -ProjectRoot $envProj))

Set-Content -LiteralPath (Join-Path $envProj '.env.example') -Value 'LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1' -Encoding utf8
Assert-True -Name '.env created from .env.example' -Condition (New-RsEnvFile -ProjectRoot $envProj)
Assert-True -Name '.env now exists'                -Condition (Test-Path -LiteralPath (Join-Path $envProj '.env'))

Set-Content -LiteralPath (Join-Path $envProj '.env') -Value 'EDITED=1' -Encoding utf8
Assert-True -Name 'existing .env is not overwritten' -Condition (-not (New-RsEnvFile -ProjectRoot $envProj))
Assert-True -Name 'user edits to .env survive' `
            -Condition ((Get-Content -LiteralPath (Join-Path $envProj '.env') -Raw) -like '*EDITED=1*')

# ==========================================================================
Write-Host "`n== Invoke-RsRetry ==" -ForegroundColor Cyan
# ==========================================================================

$script:attempts = 0
$value = Invoke-RsRetry -Description 'flaky operation' -MaxAttempts 4 -InitialDelaySeconds 1 -Action {
    $script:attempts++
    if ($script:attempts -lt 3) { throw "transient failure $($script:attempts)" }
    return 'succeeded'
}
Assert-Equal -Name 'retries until success'        -Expected 'succeeded' -Actual $value
Assert-Equal -Name 'took exactly three attempts'  -Expected 3 -Actual $script:attempts

$script:attempts2 = 0
$threw = $false
try {
    Invoke-RsRetry -Description 'always fails' -MaxAttempts 2 -InitialDelaySeconds 1 -Action {
        $script:attempts2++
        throw 'permanent failure'
    }
} catch { $threw = $true }
Assert-True  -Name 'rethrows after exhausting attempts' -Condition $threw
Assert-Equal -Name 'honoured MaxAttempts'               -Expected 2 -Actual $script:attempts2

# A retry that returns nothing must not inject $null into the caller's output.
$emitted = @(Invoke-RsRetry -Description 'silent' -MaxAttempts 1 -Action { })
Assert-Equal -Name 'no null emitted for a void action' -Expected 0 -Actual $emitted.Count

# ==========================================================================
Write-Host "`n== Invoke-RsProcess ==" -ForegroundColor Cyan
# ==========================================================================

# Use a shell that exists on whichever platform the tests run on.
$isWin = ($PSVersionTable.PSEdition -eq 'Desktop') -or
         [bool](Get-Variable -Name IsWindows -ValueOnly -ErrorAction SilentlyContinue)
if ($isWin) {
    $shell = Get-RsSystem32 'cmd.exe'
    $okArgs = @('/c', 'echo hello')
    $failArgs = @('/c', 'exit 7')
    $slowArgs = @('/c', 'ping -n 12 127.0.0.1 >nul')
} else {
    $shell = '/bin/sh'
    $okArgs = @('-c', 'echo hello')
    $failArgs = @('-c', 'exit 7')
    $slowArgs = @('-c', 'sleep 12')
}

$r = Invoke-RsProcess -FilePath $shell -Arguments $okArgs -TimeoutSeconds 60 -Quiet
Assert-Equal -Name 'captures a zero exit code' -Expected 0 -Actual $r.ExitCode
Assert-True  -Name 'captures stdout'           -Condition ($r.StdOut -like '*hello*')
Assert-True  -Name 'not marked as timed out'   -Condition (-not $r.TimedOut)

$r = Invoke-RsProcess -FilePath $shell -Arguments $failArgs -TimeoutSeconds 60 -Quiet
Assert-Equal -Name 'reports a non-zero exit code without throwing' -Expected 7 -Actual $r.ExitCode

$r = Invoke-RsProcess -FilePath $shell -Arguments $slowArgs -TimeoutSeconds 3 -Quiet
Assert-True  -Name 'kills a process that exceeds its timeout' -Condition $r.TimedOut
Assert-Equal -Name 'timed-out process reports exit code -1'   -Expected -1 -Actual $r.ExitCode

# ==========================================================================
Write-Host "`n== Test-RsVenvImports ==" -ForegroundColor Cyan
# ==========================================================================

# Exercise the import probe against whatever Python is on this machine. This is
# the check the installer uses to decide whether .venv-ui is usable, so a bug
# here reports a broken install on a perfectly good one.
$localPy = $null
foreach ($n in @('python3', 'python')) {
    $c = Get-RsCommand -Name $n
    if ($c) { $localPy = $c.Source; break }
}
if (-not $localPy) {
    Write-Host '  SKIP  no local Python available for the import probe' -ForegroundColor DarkGray
} else {
    Assert-True -Name 'import probe accepts modules that exist' `
                -Condition (Test-RsVenvImports -VenvPython $localPy -Modules @('json', 'sys', 'os'))
    Assert-True -Name 'import probe rejects a missing module' `
                -Condition (-not (Test-RsVenvImports -VenvPython $localPy -Modules @('json', 'definitely_not_a_real_module_xyz')))
    Assert-True -Name 'import probe rejects an unusable interpreter path' `
                -Condition (-not (Test-RsVenvImports -VenvPython (Join-Path $tmpRoot 'no-python.exe') -Modules @('json')))
}

# ==========================================================================
Write-Host "`n== Expand-RsArchive ==" -ForegroundColor Cyan
# ==========================================================================

Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
$srcDir = Join-Path $tmpRoot 'zipsrc'
New-Item -ItemType Directory -Path (Join-Path $srcDir 'tools\Lib') -Force | Out-Null
Set-Content -LiteralPath (Join-Path $srcDir 'tools\python.exe') -Value 'not-really-an-exe' -Encoding utf8
Set-Content -LiteralPath (Join-Path $srcDir 'tools\Lib\venv.py') -Value 'venv' -Encoding utf8
$zipPath = Join-Path $tmpRoot 'sample.zip'
[System.IO.Compression.ZipFile]::CreateFromDirectory($srcDir, $zipPath)

$outDir = Join-Path $tmpRoot 'zipout'
Expand-RsArchive -Path $zipPath -Destination $outDir -Force | Out-Null
Assert-True -Name 'archive expands nested files' `
            -Condition (Test-Path -LiteralPath (Join-Path $outDir 'tools/Lib/venv.py'))
Assert-True -Name 'archive expands top-level files' `
            -Condition (Test-Path -LiteralPath (Join-Path $outDir 'tools/python.exe'))

# Re-expanding over an existing directory must succeed (idempotent bundles).
Expand-RsArchive -Path $zipPath -Destination $outDir | Out-Null
Assert-True -Name 'expanding twice is safe' `
            -Condition (Test-Path -LiteralPath (Join-Path $outDir 'tools/python.exe'))

# ==========================================================================
Write-Host "`n== Install-RsBundledPython ==" -ForegroundColor Cyan
# ==========================================================================

# Build a synthetic bundle with the same layout as the official CPython nuget
# package, then drive the real provisioning path: hash verification, expansion
# and promotion to {app}\runtime\python.
$bundleProj = Join-Path $tmpRoot 'BundleProj'
$bundleDir = Join-Path $bundleProj 'runtime\bundle'
New-Item -ItemType Directory -Path $bundleDir -Force | Out-Null

$fakeSrc = Join-Path $tmpRoot 'fakepy'
New-Item -ItemType Directory -Path (Join-Path $fakeSrc 'tools\Lib\venv') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $fakeSrc 'tools\Lib\ensurepip') -Force | Out-Null
Set-Content -LiteralPath (Join-Path $fakeSrc 'tools\python.exe') -Value 'stub' -Encoding ascii
Set-Content -LiteralPath (Join-Path $fakeSrc 'tools\Lib\venv\__init__.py') -Value '# venv' -Encoding ascii
Set-Content -LiteralPath (Join-Path $fakeSrc 'tools\Lib\ensurepip\__init__.py') -Value '# ensurepip' -Encoding ascii

$fakeNupkg = Join-Path $bundleDir 'python-3.12.10-win-x64.nupkg'
[System.IO.Compression.ZipFile]::CreateFromDirectory($fakeSrc, $fakeNupkg)
$fakeHash = (Get-FileHash -LiteralPath $fakeNupkg -Algorithm SHA256).Hash.ToLowerInvariant()

# Correct manifest -> provisioning succeeds.
@{ python = @{ version = '3.12.10'; file = 'python-3.12.10-win-x64.nupkg'; sha256 = $fakeHash } } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $bundleDir 'bundle-manifest.json') -Encoding utf8

$provisioned = Install-RsBundledPython -ProjectRoot $bundleProj
Assert-True -Name 'bundled python provisioned from the package' -Condition ($null -ne $provisioned)
Assert-True -Name 'runtime python.exe is in place' `
            -Condition (Test-Path -LiteralPath (Join-Path $bundleProj 'runtime\python\python.exe'))
Assert-True -Name 'runtime carries the venv module' `
            -Condition (Test-Path -LiteralPath (Join-Path $bundleProj 'runtime\python\Lib\venv\__init__.py'))
Assert-True -Name 'nuget tools\ prefix is stripped' `
            -Condition (-not (Test-Path -LiteralPath (Join-Path $bundleProj 'runtime\python\tools')))

# Tampered manifest -> provisioning must refuse rather than ship a bad runtime.
@{ python = @{ version = '3.12.10'; file = 'python-3.12.10-win-x64.nupkg'
               sha256 = '0000000000000000000000000000000000000000000000000000000000000000' } } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $bundleDir 'bundle-manifest.json') -Encoding utf8
$refused = $false
try { Install-RsBundledPython -ProjectRoot $bundleProj -Force | Out-Null } catch { $refused = $true }
Assert-True -Name 'a hash mismatch is refused' -Condition $refused

# Missing bundle -> returns null so the caller can fall back to a download.
$emptyProj = Join-Path $tmpRoot 'EmptyProj'
New-Item -ItemType Directory -Path $emptyProj -Force | Out-Null
Assert-True -Name 'absent bundle returns null (caller falls back)' `
            -Condition ($null -eq (Install-RsBundledPython -ProjectRoot $emptyProj))

# ==========================================================================
Write-Host "`n== Get-RsFileHashSafe ==" -ForegroundColor Cyan
# ==========================================================================

$hashFile = Join-Path $tmpRoot 'hash.txt'
Set-Content -LiteralPath $hashFile -Value 'abc' -NoNewline -Encoding ascii
Assert-Equal -Name 'sha256 of "abc" matches the known digest' `
             -Expected 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' `
             -Actual (Get-RsFileHashSafe -Path $hashFile)
Assert-True -Name 'missing file hashes to null' `
            -Condition ($null -eq (Get-RsFileHashSafe -Path (Join-Path $tmpRoot 'does-not-exist')))

# ==========================================================================
Write-Host "`n== Bundle/runtime path helpers ==" -ForegroundColor Cyan
# ==========================================================================

Assert-True -Name 'bundle root sits under runtime\bundle' `
            -Condition ((Get-RsBundleRoot -ProjectRoot $tmpRoot) -like '*runtime*bundle*')
Assert-True -Name 'runtime python dir sits under runtime\python' `
            -Condition ((Get-RsRuntimePythonDir -ProjectRoot $tmpRoot) -like '*runtime*python*')
Assert-True -Name 'wheelhouse is null when absent' `
            -Condition ($null -eq (Get-RsWheelhouse -ProjectRoot $tmpRoot))

$wh = Join-Path $tmpRoot 'runtime\bundle\wheelhouse'
New-Item -ItemType Directory -Path $wh -Force | Out-Null
Assert-True -Name 'wheelhouse is found when present' `
            -Condition ($null -ne (Get-RsWheelhouse -ProjectRoot $tmpRoot))

# ==========================================================================
Write-Host "`n== Set-RsEnvValue / Get-RsEnvValue ==" -ForegroundColor Cyan
# ==========================================================================

$envPath = Join-Path $tmpRoot 'dotenv\.env'
New-Item -ItemType Directory -Path (Split-Path -Parent $envPath) -Force | Out-Null
@('# RedSight config', 'LOG_LEVEL=INFO', '', '# Qdrant', 'QDRANT_URL=http://127.0.0.1:6333') |
    Set-Content -LiteralPath $envPath -Encoding utf8

Assert-True  -Name 'appends a new key'          -Condition (-not (Set-RsEnvValue -Path $envPath -Key 'REDSIGHT_WORKSPACE' -Value 'C:\ws'))
Assert-Equal -Name 'new key reads back'         -Expected 'C:\ws' -Actual (Get-RsEnvValue -Path $envPath -Key 'REDSIGHT_WORKSPACE')
Assert-True  -Name 'replaces an existing key'   -Condition (Set-RsEnvValue -Path $envPath -Key 'LOG_LEVEL' -Value 'DEBUG')
Assert-Equal -Name 'replaced key reads back'    -Expected 'DEBUG' -Actual (Get-RsEnvValue -Path $envPath -Key 'LOG_LEVEL')
Assert-Equal -Name 'unrelated key untouched'    -Expected 'http://127.0.0.1:6333' -Actual (Get-RsEnvValue -Path $envPath -Key 'QDRANT_URL')
$envText = Get-Content -LiteralPath $envPath -Raw
Assert-True  -Name 'comments are preserved'     -Condition ($envText -like '*# RedSight config*' -and $envText -like '*# Qdrant*')
Assert-Equal -Name 'no duplicate key added'     -Expected 1 -Actual (@(Get-Content -LiteralPath $envPath | Where-Object { $_ -like 'LOG_LEVEL=*' }).Count)
Assert-True  -Name 'empty values are allowed'   -Condition ([bool](Set-RsEnvValue -Path $envPath -Key 'QDRANT_URL' -Value '') -or $true)
Assert-Equal -Name 'empty value reads as empty' -Expected '' -Actual (Get-RsEnvValue -Path $envPath -Key 'QDRANT_URL')
Assert-True  -Name 'missing key returns null'   -Condition ($null -eq (Get-RsEnvValue -Path $envPath -Key 'NOT_PRESENT'))

# dotenv parsers trip over a BOM in front of the first key, the same way the
# Windows INI API does.
$envBytes = [System.IO.File]::ReadAllBytes($envPath)
$envBom = ($envBytes.Length -ge 3 -and $envBytes[0] -eq 0xEF -and $envBytes[1] -eq 0xBB -and $envBytes[2] -eq 0xBF)
Assert-True -Name '.env is written without a BOM' -Condition (-not $envBom)

# ==========================================================================
Write-Host "`n== Get-RsDependencyPlan (hardware-aware wheel selection) ==" -ForegroundColor Cyan
# ==========================================================================

# The whole point: never download CUDA wheels for a machine that cannot use them.
$hwCuda = [pscustomobject]@{ gpu = [pscustomobject]@{ cudaCapable = $true;  maxVramGB = 24.0; hasNvidiaHardware = $true } }
$hwNone = [pscustomobject]@{ gpu = [pscustomobject]@{ cudaCapable = $false; maxVramGB = 0.0;  hasNvidiaHardware = $false } }
$hwStale = [pscustomobject]@{ gpu = [pscustomobject]@{ cudaCapable = $false; maxVramGB = 0.0; hasNvidiaHardware = $true } }
$hwTiny = [pscustomobject]@{ gpu = [pscustomobject]@{ cudaCapable = $true;  maxVramGB = 2.0;  hasNvidiaHardware = $true } }

function Get-PlanArgs { param($Plan) ; return (($Plan.PreInstalls | ForEach-Object { $_.Args -join ' ' }) -join ' | ') }

$planCuda = Get-RsDependencyPlan -SetupProfile 'auto' -Hardware $hwCuda
Assert-Equal -Name 'auto picks cuda on a real NVIDIA GPU' -Expected 'cuda' -Actual $planCuda.Profile
Assert-True  -Name 'cuda plan uses the cu124 wheel index' -Condition ((Get-PlanArgs $planCuda) -like '*download.pytorch.org/whl/cu124*')
Assert-True  -Name 'cuda plan installs onnxruntime-gpu'   -Condition ((Get-PlanArgs $planCuda) -like '*onnxruntime-gpu*')

$planNone = Get-RsDependencyPlan -SetupProfile 'auto' -Hardware $hwNone
Assert-Equal -Name 'auto picks api with no GPU'           -Expected 'api' -Actual $planNone.Profile
Assert-True  -Name 'api plan uses the CPU wheel index'    -Condition ((Get-PlanArgs $planNone) -like '*download.pytorch.org/whl/cpu*')
Assert-True  -Name 'api plan never pulls CUDA wheels'     -Condition ((Get-PlanArgs $planNone) -notlike '*cu124*')
Assert-True  -Name 'api plan avoids onnxruntime-gpu'      -Condition ((Get-PlanArgs $planNone) -notlike '*onnxruntime-gpu*')

$planStale = Get-RsDependencyPlan -SetupProfile 'auto' -Hardware $hwStale
Assert-Equal -Name 'NVIDIA card with no driver falls back to api' -Expected 'api' -Actual $planStale.Profile
Assert-True  -Name 'and says why'                         -Condition ($planStale.Reason -like '*driver*')

$planTiny = Get-RsDependencyPlan -SetupProfile 'auto' -Hardware $hwTiny
Assert-Equal -Name 'a 2 GB GPU is not worth CUDA wheels'  -Expected 'api' -Actual $planTiny.Profile

$planForced = Get-RsDependencyPlan -SetupProfile 'cuda' -Hardware $hwNone
Assert-Equal -Name 'explicit cuda is honoured'            -Expected 'cuda' -Actual $planForced.Profile
Assert-True  -Name 'but warns there is no driver'         -Condition ($planForced.Reason -like '*no working NVIDIA driver*')

$planApiOnGpu = Get-RsDependencyPlan -SetupProfile 'api' -Hardware $hwCuda
Assert-Equal -Name 'explicit api is honoured on a GPU box' -Expected 'api' -Actual $planApiOnGpu.Profile

$planNoHw = Get-RsDependencyPlan -SetupProfile 'auto' -Hardware $null
Assert-Equal -Name 'no hardware info degrades to api'     -Expected 'api' -Actual $planNoHw.Profile

# ==========================================================================
Write-Host "`n== Initialize-RsWorkspace ==" -ForegroundColor Cyan
# ==========================================================================

$wsProj = Join-Path $tmpRoot 'WsProj'
New-Item -ItemType Directory -Path $wsProj -Force | Out-Null
$wsDir = Join-Path $tmpRoot 'RedSightWorkspace'

$created = Initialize-RsWorkspace -ProjectRoot $wsProj -WorkspaceDir $wsDir -NativeMode
Assert-Equal -Name 'returns the workspace path' -Expected $wsDir -Actual $created
foreach ($sub in @('workspace', 'projects', 'inbox', 'outputs', 'memory', 'logs', 'mcp', 'data')) {
    Assert-True -Name "creates $sub\" -Condition (Test-Path -LiteralPath (Join-Path $wsDir $sub))
}
Assert-True -Name 'writes a README into the workspace' -Condition (Test-Path -LiteralPath (Join-Path $wsDir 'README.txt'))

$wsEnv = Join-Path $wsProj '.env'
Assert-Equal -Name 'REDSIGHT_WORKSPACE written'   -Expected $wsDir -Actual (Get-RsEnvValue -Path $wsEnv -Key 'REDSIGHT_WORKSPACE')
Assert-Equal -Name 'REDSIGHT_WORKING_DIR written' -Expected (Join-Path $wsDir 'workspace') -Actual (Get-RsEnvValue -Path $wsEnv -Key 'REDSIGHT_WORKING_DIR')
Assert-Equal -Name 'REDSIGHT_MCP_DIR written'     -Expected (Join-Path $wsDir 'mcp') -Actual (Get-RsEnvValue -Path $wsEnv -Key 'REDSIGHT_MCP_DIR')
Assert-Equal -Name 'native mode sets the data root' -Expected (Join-Path $wsDir 'data') -Actual (Get-RsEnvValue -Path $wsEnv -Key 'RED_SIGHT_DATA_ROOT')

# Re-running must not duplicate anything or clobber a user edit.
Set-Content -LiteralPath (Join-Path $wsDir 'README.txt') -Value 'user edited' -Encoding utf8
$again2 = Initialize-RsWorkspace -ProjectRoot $wsProj -WorkspaceDir $wsDir -NativeMode
Assert-Equal -Name 'workspace init is idempotent' -Expected $wsDir -Actual $again2
Assert-True  -Name 'does not overwrite an edited README' `
             -Condition ((Get-Content -LiteralPath (Join-Path $wsDir 'README.txt') -Raw) -like '*user edited*')
Assert-Equal -Name 'no duplicate env entries on re-run' -Expected 1 `
             -Actual (@(Get-Content -LiteralPath $wsEnv | Where-Object { $_ -like 'REDSIGHT_WORKSPACE=*' }).Count)

# Container mode must leave RED_SIGHT_DATA_ROOT alone (compose supplies /data).
$wsProj2 = Join-Path $tmpRoot 'WsProj2'
New-Item -ItemType Directory -Path $wsProj2 -Force | Out-Null
Initialize-RsWorkspace -ProjectRoot $wsProj2 -WorkspaceDir (Join-Path $tmpRoot 'Ws2') | Out-Null
Assert-True -Name 'container mode leaves RED_SIGHT_DATA_ROOT unset' `
            -Condition ($null -eq (Get-RsEnvValue -Path (Join-Path $wsProj2 '.env') -Key 'RED_SIGHT_DATA_ROOT'))

# ==========================================================================
Write-Host "`n== Install-RsMcpConfig ==" -ForegroundColor Cyan
# ==========================================================================

$mcpSrc = Join-Path $tmpRoot 'mcp-source'
New-Item -ItemType Directory -Path $mcpSrc -Force | Out-Null
Set-Content -LiteralPath (Join-Path $mcpSrc 'servers.json') -Value '{"mcp_servers":{"demo":{"url":"http://localhost:40404/mcp"}}}' -Encoding utf8
Set-Content -LiteralPath (Join-Path $mcpSrc 'extra.yaml') -Value "mcp_servers:`n  other:`n    command: node" -Encoding utf8
Set-Content -LiteralPath (Join-Path $mcpSrc 'notes.md') -Value 'ignored' -Encoding utf8

$n = Install-RsMcpConfig -SourcePath $mcpSrc -WorkspaceDir $wsDir
Assert-Equal -Name 'copies both MCP definition files' -Expected 2 -Actual $n
Assert-True  -Name 'json definition registered' -Condition (Test-Path -LiteralPath (Join-Path $wsDir 'mcp\servers.json'))
Assert-True  -Name 'yaml definition registered' -Condition (Test-Path -LiteralPath (Join-Path $wsDir 'mcp\extra.yaml'))
Assert-True  -Name 'unrelated files ignored'    -Condition (-not (Test-Path -LiteralPath (Join-Path $wsDir 'mcp\notes.md')))

$single = Install-RsMcpConfig -SourcePath (Join-Path $mcpSrc 'servers.json') -WorkspaceDir $wsDir
Assert-Equal -Name 'accepts a single file path' -Expected 1 -Actual $single

$mcpThrew = $false
try { Install-RsMcpConfig -SourcePath (Join-Path $tmpRoot 'no-such-mcp') -WorkspaceDir $wsDir | Out-Null }
catch { $mcpThrew = $true }
Assert-True -Name 'rejects a missing MCP path' -Condition $mcpThrew

$emptyMcp = Join-Path $tmpRoot 'mcp-empty'
New-Item -ItemType Directory -Path $emptyMcp -Force | Out-Null
$emptyThrew = $false
try { Install-RsMcpConfig -SourcePath $emptyMcp -WorkspaceDir $wsDir | Out-Null } catch { $emptyThrew = $true }
Assert-True -Name 'rejects a directory with no definitions' -Condition $emptyThrew

# ==========================================================================
Write-Host "`n== Set-RsProviderConfig ==" -ForegroundColor Cyan
# ==========================================================================

# Contain the writes: the function targets %LOCALAPPDATA%\RedSight\settings.
$savedLocalAppData = $env:LOCALAPPDATA
$env:LOCALAPPDATA = Join-Path $tmpRoot 'localappdata'
New-Item -ItemType Directory -Path $env:LOCALAPPDATA -Force | Out-Null
try {
    Set-RsProviderConfig -Provider 'openai' -ApiKey 'sk-test-not-a-real-key' -Model 'gpt-5.6-terra' | Out-Null
    $provFile = Join-Path $env:LOCALAPPDATA 'RedSight\settings\provider.json'
    Assert-True -Name 'provider.json written where Settings reads it' -Condition (Test-Path -LiteralPath $provFile)

    $prov = Get-Content -LiteralPath $provFile -Raw | ConvertFrom-Json
    Assert-Equal -Name 'active_provider recorded' -Expected 'openai' -Actual $prov.active_provider
    Assert-Equal -Name 'schema version matches the app' -Expected 1 -Actual $prov.version
    Assert-Equal -Name 'model recorded for the provider' -Expected 'gpt-5.6-terra' -Actual $prov.models.openai
    Assert-True  -Name 'defaults kept for other providers' -Condition ([bool]$prov.models.anthropic)
    Assert-True  -Name 'custom_base_url present' -Condition ($null -ne $prov.PSObject.Properties['custom_base_url'])

    # Switching provider must preserve the other providers' models.
    Set-RsProviderConfig -Provider 'anthropic' -Model 'claude-sonnet-5' | Out-Null
    $prov2 = Get-Content -LiteralPath $provFile -Raw | ConvertFrom-Json
    Assert-Equal -Name 'provider switch recorded' -Expected 'anthropic' -Actual $prov2.active_provider
    Assert-Equal -Name 'previous provider model preserved' -Expected 'gpt-5.6-terra' -Actual $prov2.models.openai

    # lmstudio is local and takes no key.
    Set-RsProviderConfig -Provider 'lmstudio' | Out-Null
    $prov3 = Get-Content -LiteralPath $provFile -Raw | ConvertFrom-Json
    Assert-Equal -Name 'lmstudio selectable without a key' -Expected 'lmstudio' -Actual $prov3.active_provider
} finally {
    if ($savedLocalAppData) { $env:LOCALAPPDATA = $savedLocalAppData } else { Remove-Item Env:\LOCALAPPDATA -ErrorAction SilentlyContinue }
}

# ==========================================================================
Write-Host "`n== Test-RsUiLaunch ==" -ForegroundColor Cyan
# ==========================================================================

# Build a stand-in for the Command Center import chain so the probe's real code
# path runs without a Qt install. This is the check that answers "why did the UI
# not launch?", so its failure reporting matters as much as its success case.
$uiPy = $null
foreach ($n in @('python3', 'python')) {
    $c = Get-RsCommand -Name $n
    if ($c) { $uiPy = $c.Source; break }
}
if (-not $uiPy) {
    Write-Host '  SKIP  no local Python for the UI launch probe' -ForegroundColor DarkGray
} else {
    $uiRoot = Join-Path $tmpRoot 'FakeUi'
    New-Item -ItemType Directory -Path (Join-Path $uiRoot 'PySide6') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $uiRoot 'qasync') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $uiRoot 'app\ui') -Force | Out-Null

    Set-Content -LiteralPath (Join-Path $uiRoot 'PySide6\__init__.py') -Value '' -Encoding ascii
    Set-Content -LiteralPath (Join-Path $uiRoot 'PySide6\QtWidgets.py') -Encoding ascii -Value @(
        'class QApplication:',
        '    @staticmethod',
        '    def instance(): return None',
        '    def __init__(self, argv=None): pass'
    )
    Set-Content -LiteralPath (Join-Path $uiRoot 'qasync\__init__.py') -Value '' -Encoding ascii
    Set-Content -LiteralPath (Join-Path $uiRoot 'app\__init__.py') -Value '' -Encoding ascii
    Set-Content -LiteralPath (Join-Path $uiRoot 'app\ui\__init__.py') -Value '' -Encoding ascii
    Set-Content -LiteralPath (Join-Path $uiRoot 'app\ui\qt_bootstrap.py') -Encoding ascii -Value @(
        'def configure_qt_pre_application():',
        '    return True'
    )
    Set-Content -LiteralPath (Join-Path $uiRoot 'app\ui\command_center.py') -Encoding ascii -Value @(
        'class CommandCenterMainWindow:',
        '    pass'
    )

    $ok = Test-RsUiLaunch -VenvPython $uiPy -ProjectRoot $uiRoot
    Assert-True  -Name 'a healthy UI chain reports success' -Condition $ok.Ok
    Assert-True  -Name 'success says so in plain words'     -Condition ($ok.Detail -like '*loads cleanly*')
    Assert-Equal -Name 'no traceback on success'            -Expected '' -Actual $ok.Traceback

    # The 11.1 regression in miniature: the environment resolves but a module raises.
    Set-Content -LiteralPath (Join-Path $uiRoot 'app\ui\command_center.py') -Encoding ascii -Value @(
        'raise ImportError("No module named ''qasync''")'
    )
    $bad = Test-RsUiLaunch -VenvPython $uiPy -ProjectRoot $uiRoot
    Assert-True -Name 'a broken UI chain reports failure'   -Condition (-not $bad.Ok)
    Assert-True -Name 'and names the stage that failed'     -Condition ($bad.Detail -like '*command_center*')
    Assert-True -Name 'and captures the traceback'          -Condition ($bad.Traceback -like '*ImportError*')

    # A missing qasync must be caught before the app is declared ready.
    Remove-Item -LiteralPath (Join-Path $uiRoot 'qasync') -Recurse -Force
    $noQasync = Test-RsUiLaunch -VenvPython $uiPy -ProjectRoot $uiRoot
    Assert-True -Name 'a missing qasync fails the probe'    -Condition (-not $noQasync.Ok)
    Assert-True -Name 'and points at qasync'                -Condition ($noQasync.Detail -like '*qasync*')

    Assert-True -Name 'a missing interpreter fails cleanly' `
                -Condition (-not (Test-RsUiLaunch -VenvPython (Join-Path $tmpRoot 'no-python.exe') -ProjectRoot $uiRoot).Ok)
}

# ==========================================================================
Write-Host "`n== RedSight-Hardware.ps1 ==" -ForegroundColor Cyan
# ==========================================================================

# The scanner must produce a usable, conservative profile even where none of
# the Windows APIs it queries exist - it runs before anything is installed.
$hwScript = Join-Path $scripts 'RedSight-Hardware.ps1'
Assert-True -Name 'hardware scanner is present' -Condition (Test-Path -LiteralPath $hwScript)

$hwOut = Join-Path $tmpRoot 'hw.json'
$pwshExe = (Get-Process -Id $PID).Path
$hwProc = Invoke-RsProcess -FilePath $pwshExe `
                           -Arguments @('-NoLogo', '-NoProfile', '-File', $hwScript, '-Quiet', '-OutFile', $hwOut) `
                           -TimeoutSeconds 180 -Quiet
Assert-Equal -Name 'hardware scan exits 0 even when degraded' -Expected 0 -Actual $hwProc.ExitCode
Assert-True  -Name 'hardware scan writes its profile' -Condition (Test-Path -LiteralPath $hwOut)

if (Test-Path -LiteralPath $hwOut) {
    $hwJson = Get-Content -LiteralPath $hwOut -Raw | ConvertFrom-Json
    foreach ($key in @('os', 'cpu', 'gpu', 'virtualization', 'recommend', 'warnings')) {
        Assert-True -Name "profile has a '$key' section" -Condition ($null -ne $hwJson.PSObject.Properties[$key])
    }
    Assert-True -Name 'recommends a known setup profile' `
                -Condition ($hwJson.recommend.setupProfile -in @('cuda', 'api'))
    Assert-True -Name 'recommends a known runtime mode' `
                -Condition ($hwJson.recommend.runtimeMode -in @('container', 'native'))
    Assert-True -Name 'reports a wsl2Capable verdict' `
                -Condition ($hwJson.virtualization.PSObject.Properties['wsl2Capable'] -ne $null)
    foreach ($gk in @('nvidiaGpuCount', 'totalVramGB', 'names', 'nvidia')) {
        Assert-True -Name "gpu section reports '$gk'" `
                    -Condition ($null -ne $hwJson.gpu.PSObject.Properties[$gk])
    }
    Assert-True -Name 'explains any WSL2 blocker' `
                -Condition ($hwJson.virtualization.wsl2Capable -or [bool]$hwJson.virtualization.wsl2Blocker)
}

$hwIni = Join-Path $tmpRoot 'hw.ini'
$iniProc = Invoke-RsProcess -FilePath $pwshExe `
                            -Arguments @('-NoLogo', '-NoProfile', '-File', $hwScript, '-Quiet', '-IniFile', $hwIni) `
                            -TimeoutSeconds 180 -Quiet
Assert-Equal -Name 'hardware scan writes the wizard INI' -Expected 0 -Actual $iniProc.ExitCode
if (Test-Path -LiteralPath $hwIni) {
    $iniText = Get-Content -LiteralPath $hwIni -Raw
    # These are exactly the keys RedSight.iss reads with GetIniString.
    foreach ($key in @('cudaCapable', 'hasNvidiaHardware', 'nvidiaGpuCount', 'gpuNames',
                       'maxVramGB', 'totalVramGB', 'wsl2Capable', 'wsl2Blocker',
                       'recommendProfile', 'recommendRuntime', 'isLaptop')) {
        Assert-True -Name "wizard INI carries '$key'" -Condition ($iniText -match "(?m)^$key=")
    }
    # The regression that broke a real install: Windows PowerShell 5.1 writes a
    # BOM with -Encoding utf8, and the Windows INI API then fails to match the
    # first section header, so every GetIniString returns its default.
    $iniBytes = [System.IO.File]::ReadAllBytes($hwIni)
    $hasBom = ($iniBytes.Length -ge 3 -and $iniBytes[0] -eq 0xEF -and $iniBytes[1] -eq 0xBB -and $iniBytes[2] -eq 0xBF)
    Assert-True -Name 'wizard INI has no UTF-8 BOM' -Condition (-not $hasBom)
    Assert-True -Name 'wizard INI starts with the section header' `
                -Condition ($iniText.StartsWith('[hardware]'))
    Assert-True -Name 'wizard INI carries the scanOk sentinel' -Condition ($iniText -match '(?m)^scanOk=1')

    Assert-True -Name 'INI values are single-line' `
                -Condition (@($iniText -split "`r?`n" | Where-Object { $_ -and ($_ -notmatch '^\[') -and ($_ -notmatch '=') }).Count -eq 0)
}

# ==========================================================================
Write-Host "`n== Logging and summary ==" -ForegroundColor Cyan
# ==========================================================================

$logDir = Join-Path $tmpRoot 'logs'
$log = Initialize-RsLog -Name 'unittest' -LogDir $logDir
Assert-True -Name 'log file is created' -Condition (Test-Path -LiteralPath $log)
Write-RsLog 'a test log line' -Level OK
Assert-True -Name 'log line is persisted' `
            -Condition ((Get-Content -LiteralPath $log -Raw) -like '*a test log line*')

Set-RsSummary -Key 'answer' -Value 42
$summaryPath = Join-Path $tmpRoot 'summary.json'
Save-RsSummary -Path $summaryPath
Assert-True -Name 'summary json is written' -Condition (Test-Path -LiteralPath $summaryPath)
$parsed = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
Assert-Equal -Name 'summary round-trips values' -Expected 42 -Actual $parsed.answer

} finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}

# ==========================================================================
Write-Host ("`n" + ('=' * 60)) -ForegroundColor Cyan
Write-Host ("  {0} passed, {1} failed" -f $script:Pass, $script:Fail) -ForegroundColor $(if ($script:Fail) { 'Red' } else { 'Green' })
Write-Host ('=' * 60) -ForegroundColor Cyan
if ($script:Fail) {
    Write-Host "`nFailures:" -ForegroundColor Red
    foreach ($f in $script:Failures) { Write-Host "  - $f" -ForegroundColor Red }
    exit 1
}
exit 0
