#requires -version 5.1
[CmdletBinding()]
param(
  [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
  [string]$OutputRoot = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path 'dist\windows-v6'),
  [switch]$BundleOfflineDependencies,
  [switch]$SkipDockerPayload,
  [string]$AppVersion = '11.5.5.6'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Fail([string]$m) { throw $m }
if (-not (Test-Path (Join-Path $SourceRoot 'pyproject.toml'))) { Fail "SourceRoot does not look like RedSight: $SourceRoot" }
if (-not [Environment]::Is64BitOperatingSystem) { Fail 'Build host must be 64-bit Windows.' }
function Find-InnoCompiler {
  $pf86 = ${env:ProgramFiles(x86)}
  $candidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
    (Join-Path ${env:ProgramFiles} 'Inno Setup 7\ISCC.exe'),
    (Join-Path $pf86 'Inno Setup 7\ISCC.exe'),
    (Join-Path ${env:ProgramFiles} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $pf86 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
  if ($candidates) { return ($candidates | Select-Object -First 1) }
  $roots = @(${env:ProgramFiles}, $pf86, $env:LOCALAPPDATA) | Where-Object { $_ -and (Test-Path $_) }
  foreach ($root in $roots) { $found = Get-ChildItem -LiteralPath $root -Filter ISCC.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1; if ($found) { return $found.FullName } }
  return $null
}
$inno = Find-InnoCompiler
if (-not $inno) {
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) { Fail 'Inno Setup is missing and winget.exe is unavailable. Install Inno Setup 6 or 7 and rerun.' }
  Write-Host 'Inno Setup compiler not found. Installing the official Inno Setup package...'
  & winget install --id JRSoftware.InnoSetup.7 -e -s winget --silent --accept-source-agreements --accept-package-agreements | Out-Host
  $inno = Find-InnoCompiler
}
if (-not $inno) { Fail 'Inno Setup installation completed but ISCC.exe could not be located.' }
Write-Host "Using Inno Setup compiler: $inno"
Remove-Item $OutputRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$buildId = [guid]::NewGuid().ToString('N')
$stage = Join-Path $env:TEMP "RedSight-v6-stage-$buildId"
$offline = Join-Path $stage 'offline'
$setupDir = Join-Path $OutputRoot 'installer'
$artifacts = Join-Path $OutputRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $stage, $setupDir, $artifacts | Out-Null
try {
  $excludeDirs = @('.git','.venv','.venv-ui','.venv-actions','data','outputs','dist','__pycache__','tests')
  $excludeFiles = @('*.pyc','*.pyo','*.log','*.sqlite','*.db')
  $robocopyArgs = @($SourceRoot,$stage,'/E','/R:2','/W:1','/NFL','/NDL','/NJH','/NJS','/NP')
  foreach ($d in $excludeDirs) { $robocopyArgs += '/XD'; $robocopyArgs += (Join-Path $SourceRoot $d) }
  # /XF consumes file-name patterns. Do not append source-qualified paths or robocopy treats them as stray parameters.
  $robocopyArgs += '/XF'
  $robocopyArgs += $excludeFiles
  & robocopy.exe @robocopyArgs | Out-Host
  $rc = $LASTEXITCODE
  if ($rc -gt 7) { Fail "robocopy failed with exit code $rc. Source=$SourceRoot Stage=$stage" }
  $required = @('pyproject.toml','app\server.py','ui\command_center.py','redsight_actions\gateway.py','scripts\windows\RedSight-Setup-Resume.ps1','scripts\windows\RedSight-PostInstall-Health.ps1','scripts\windows\Start-RedSight.ps1','assets\redsight.ico')
  foreach ($r in $required) { if (-not (Test-Path (Join-Path $stage $r))) { Fail "Required runtime file missing: $r" } }
  $tools = Join-Path $stage 'tools'; $site = Join-Path $tools 'Lib\site-packages'
  New-Item -ItemType Directory -Force -Path $tools, $site | Out-Null
  $pyPkg = Join-Path $env:TEMP 'redsight-python-3.12.10.nupkg'; $pyExtract = Join-Path $env:TEMP "redsight-python-extract-$buildId"
  Remove-Item $pyExtract -Recurse -Force -ErrorAction SilentlyContinue
  Invoke-WebRequest 'https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg' -OutFile $pyPkg -UseBasicParsing
  Expand-Archive -LiteralPath $pyPkg -DestinationPath $pyExtract -Force
  Copy-Item (Join-Path $pyExtract 'tools\*') $tools -Recurse -Force
  Remove-Item $pyPkg, $pyExtract -Recurse -Force -ErrorAction SilentlyContinue
  $pyExe = Join-Path $tools 'python.exe'; if (-not (Test-Path $pyExe)) { Fail 'Bundled Python runtime was not produced.' }
  $pv = & $pyExe --version 2>&1 | Out-String; if ($pv -notmatch 'Python 3\.12') { Fail "Unexpected bundled Python version: $pv" }
  $buildPython = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($buildPython) { $pyHost = (& py.exe -3.12 --version 2>&1 | Out-String).Trim(); if ($pyHost -notmatch '^Python 3\.12') { $buildPython = $null } }
  if ($buildPython) { $hostPython = 'py.exe'; $hostPythonArgs = @('-3.12') } else {
    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) { $pyHost = (& $pythonCmd.Source --version 2>&1 | Out-String).Trim(); if ($pyHost -notmatch '^Python 3\.12') { $pythonCmd = $null } }
    if (-not $pythonCmd) { $winget = Get-Command winget.exe -ErrorAction SilentlyContinue; if (-not $winget) { Fail 'Python 3.12 is required on the build host to populate bundled dependencies.' }; & winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements | Out-Host; $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue }
    if (-not $pythonCmd) { Fail 'Python 3.12 installation completed but python.exe is not available in this PowerShell session. Restart PowerShell and rerun the build.' }
    $hostPython = $pythonCmd.Source; $hostPythonArgs = @()
  }
  Write-Host 'Installing RedSight runtime dependencies into the bundled Python payload...'
  & $hostPython @hostPythonArgs -m pip install --upgrade pip --disable-pip-version-check | Out-Host
  if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed with exit code $LASTEXITCODE" }
  & $hostPython @hostPythonArgs -m pip install --disable-pip-version-check --no-user --upgrade --target $site $stage | Out-Host
  if ($LASTEXITCODE -ne 0) { Fail "Python dependency installation failed with exit code $LASTEXITCODE" }
  $env:PLAYWRIGHT_BROWSERS_PATH = '0'
  try { & $hostPython @hostPythonArgs -m playwright install chromium | Out-Host; if ($LASTEXITCODE -ne 0) { Fail "Playwright Chromium installation failed with exit code $LASTEXITCODE" } } finally { Remove-Item Env:PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue }
  if ($BundleOfflineDependencies) {
    New-Item -ItemType Directory -Force -Path $offline | Out-Null
    $rel = Invoke-RestMethod 'https://api.github.com/repos/microsoft/WSL/releases/latest' -Headers @{Accept='application/vnd.github+json';'User-Agent'='RedSight-Build'}
    $a = $rel.assets | Where-Object { $_.name -match '\.x64\.msi$' } | Sort-Object name -Descending | Select-Object -First 1
    if (-not $a) { Fail 'Could not locate latest Microsoft WSL x64 MSI.' }
    Invoke-WebRequest $a.browser_download_url -OutFile (Join-Path $offline 'wsl-latest-x64.msi') -UseBasicParsing
    if (-not $SkipDockerPayload) { Invoke-WebRequest 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe' -OutFile (Join-Path $offline 'Docker-Desktop-Installer-x64.exe') -UseBasicParsing }
  }
  $iss = Join-Path $setupDir 'RedSight-v6.iss'
  $issText = @"
#define AppName "RedSight"
#define AppVersion "$AppVersion"
#define SourceRoot "$stage"
#define OutputRoot "$artifacts"
[Setup]
AppId={{E3B9B1E4-6E56-4C6D-9B6E-6D9A5A17C6F1}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=RedSight
AppPublisherURL=https://github.com/mynomadshop/RED-SIGHT
DefaultDirName={autopf}\RedSight
DefaultGroupName=RedSight
OutputDir={#OutputRoot}
OutputBaseFilename=RedSight-Setup-v6
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupArchitecture=x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\assets\redsight.ico
SetupLogging=yes
RestartIfNeededByRun=no
CloseApplications=yes
ChangesEnvironment=no
VersionInfoVersion={#AppVersion}
VersionInfoCompany=RedSight
VersionInfoDescription=RedSight Windows v6 Installer
VersionInfoProductName=RedSight
VersionInfoProductVersion={#AppVersion}
[Files]
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Dirs]
Name: "{app}\data"
Name: "{app}\outputs"
[Icons]
Name: "{autoprograms}\RedSight\RedSight Command Center"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\Start-RedSight.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\redsight.ico"
Name: "{autodesktop}\RedSight Command Center"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\Start-RedSight.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\redsight.ico"
[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\RedSight-Setup-Resume.ps1"" -InstallRoot ""{app}"""; WorkingDir: "{app}"; StatusMsg: "Configuring WSL2, Docker Desktop and RedSight..."; Flags: waituntilterminated
"@
  Set-Content -LiteralPath $iss -Value $issText -Encoding UTF8
  & $inno /Qp /O+ $iss | Out-Host
  $isccExit = $LASTEXITCODE
  if ($isccExit -ne 0) { Fail "Inno Setup compilation failed with exit code $isccExit. Script: $iss" }
  $exe = Join-Path $artifacts 'RedSight-Setup-v6.exe'; if (-not (Test-Path $exe)) { Fail 'Installer EXE was not produced.' }
  $hash = (Get-FileHash -Algorithm SHA256 $exe).Hash.ToLowerInvariant(); $size = (Get-Item $exe).Length
  if ($size -lt 100KB) { Fail "Installer EXE is unexpectedly small: $size bytes" }
  $manifest = [ordered]@{ product='RedSight'; distribution='Windows v6'; sourceVersion='11.5.5'; installerVersion=$AppVersion; builtAt=(Get-Date).ToUniversalTime().ToString('o'); architecture='x64'; installer='RedSight-Setup-v6.exe'; size_bytes=$size; sha256=$hash; wsl='WSL2 enabled/provisioned by resumable bootstrapper'; docker='Docker Desktop WSL2 backend provisioned by resumable bootstrapper'; offline_bundle=[bool]$BundleOfflineDependencies; python='3.12.10 private runtime with packaged dependencies'; playwright='Chromium bundled'; notes='Windows x64 distribution. WSL2 requires hardware virtualization. Online mode downloads current Microsoft WSL and Docker Desktop components.' }
  $manifest | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $artifacts 'manifest-v6.json') -Encoding UTF8
  "$hash  RedSight-Setup-v6.exe" | Set-Content (Join-Path $artifacts 'SHA256SUMS-v6.txt') -Encoding ASCII
  $readme = "RedSight Windows v6 distribution`r`n`r`nInstaller: RedSight-Setup-v6.exe`r`nSHA256: $hash`r`nArchitecture: Windows x64`r`n`r`nThe installer enables WSL2, restarts only when required, resumes automatically after logon, provisions Docker Desktop for WSL2, packages its Python runtime and runtime dependencies, bundles Playwright Chromium, and runs a post-install health gate. Online mode downloads current Microsoft WSL and Docker components. Use -BundleOfflineDependencies for a larger offline-capable build.`r`n"
  Set-Content (Join-Path $artifacts 'README.txt') $readme -Encoding UTF8
  $zip = Join-Path $OutputRoot 'RedSight-Windows-v6.zip'
  Compress-Archive -Path (Join-Path $artifacts '*') -DestinationPath $zip -CompressionLevel Optimal -Force
  if (-not (Test-Path $zip)) { Fail 'Distribution ZIP was not produced.' }
  Write-Host "`nBUILD COMPLETE`nInstaller: $exe`nZIP: $zip`nSHA256: $hash`n" -ForegroundColor Green
} finally {
  Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}
