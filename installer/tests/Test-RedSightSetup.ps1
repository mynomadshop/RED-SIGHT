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
    $shell = Join-Path $env:WINDIR 'System32\cmd.exe'
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
