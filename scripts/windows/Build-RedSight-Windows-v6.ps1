#requires -version 5.1
<#!
Builds the hardened RedSight Windows v6 distribution from the current checkout.
The build is reproducible: it stages only runtime files, creates an explicit
Inno Setup script, compiles with ISCC, hashes the EXE, and emits a ZIP manifest.

Default mode keeps WSL/Docker installers out of the payload and downloads them
on demand from Microsoft/Docker during setup. Use -BundleOfflineDependencies to
make a much larger offline-capable distribution.
#>
[CmdletBinding()]
param(
  [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
  [string]$OutputRoot = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path 'dist\windows-v6'),
  [switch]$BundleOfflineDependencies,
  [switch]$SkipDockerPayload,
  [string]$AppVersion = '11.5.5.6'
)
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
function Fail([string]$m){throw $m}
if(-not(Test-Path(Join-Path $SourceRoot 'pyproject.toml'))){Fail "SourceRoot does not look like RedSight: $SourceRoot"}
if(-not[Environment]::Is64BitOperatingSystem){Fail 'Build host must be 64-bit Windows.'}
$inno=@('C:\Program Files\Inno Setup 7\ISCC.exe','C:\Program Files (x86)\Inno Setup 6\ISCC.exe','C:\Program Files\Inno Setup 6\ISCC.exe')|Where-Object{Test-Path $_}|Select-Object -First 1
if(-not$inno){$winget=Get-Command winget.exe -ErrorAction SilentlyContinue;if($winget){Write-Host 'Inno Setup not found; installing the current 64-bit Inno Setup compiler.';& winget install --id JRSoftware.InnoSetup.7 -e --silent --accept-source-agreements --accept-package-agreements|Out-Host;$inno=@('C:\Program Files\Inno Setup 7\ISCC.exe','C:\Program Files\Inno Setup 6\ISCC.exe','C:\Program Files (x86)\Inno Setup 6\ISCC.exe')|Where-Object{Test-Path $_}|Select-Object -First 1};if(-not$inno){Fail 'Inno Setup ISCC.exe is required. Install Inno Setup 7 x64 and rerun.'}}
Remove-Item $OutputRoot -Recurse -Force -ErrorAction SilentlyContinue
$stage=Join-Path $OutputRoot 'payload';$offline=Join-Path $stage 'offline';$setupDir=Join-Path $OutputRoot 'installer';$artifacts=Join-Path $OutputRoot 'artifacts';New-Item -ItemType Directory -Force -Path $stage,$setupDir,$artifacts|Out-Null
$excludeDirs=@('.git','.venv','.venv-ui','.venv-actions','data','outputs','dist','__pycache__','tests');$excludeFiles=@('*.pyc','*.pyo','*.log','*.sqlite','*.db')
$robocopyArgs=@($SourceRoot,$stage,'/E','/R:2','/W:1','/NFL','/NDL','/NJH','/NJS','/NP');foreach($d in $excludeDirs){$robocopyArgs+='/XD';$robocopyArgs+=(Join-Path $SourceRoot $d)};foreach($f in $excludeFiles){$robocopyArgs+='/XF';$robocopyArgs+=(Join-Path $SourceRoot $f)}
& robocopy.exe @robocopyArgs|Out-Null;if($LASTEXITCODE -gt 7){Fail "robocopy failed with exit code $LASTEXITCODE"}
# Build-time integrity checks prevent a broken source tree from becoming an installer.
$required=@('pyproject.toml','app\server.py','ui\command_center.py','redsight_actions\gateway.py','scripts\windows\RedSight-Setup-Resume.ps1','scripts\windows\RedSight-PostInstall-Health.ps1');foreach($r in $required){if(-not(Test-Path(Join-Path $stage $r))){Fail "Required runtime file missing: $r"}}
if($BundleOfflineDependencies){New-Item -ItemType Directory -Force -Path $offline|Out-Null;Write-Host 'Bundling latest official WSL x64 MSI.';$rel=Invoke-RestMethod 'https://api.github.com/repos/microsoft/WSL/releases/latest' -Headers @{Accept='application/vnd.github+json';'User-Agent'='RedSight-Build'};$a=$rel.assets|Where-Object{$_.name -match '\.x64\.msi$'}|Select-Object -First 1;if(-not$a){Fail 'Could not locate latest Microsoft WSL x64 MSI.'};Invoke-WebRequest $a.browser_download_url -OutFile (Join-Path $offline 'wsl-latest-x64.msi') -UseBasicParsing;if(-not$SkipDockerPayload){Write-Host 'Bundling Docker Desktop x64 installer.';Invoke-WebRequest 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe' -OutFile (Join-Path $offline 'Docker-Desktop-Installer-x64.exe') -UseBasicParsing}}
$iss=Join-Path $setupDir 'RedSight-v6.iss';$issText=@"
#define AppName "RedSight"
#define AppVersion "$AppVersion"
#define SourceRoot "$($stage.Replace('\','\\'))"
#define OutputRoot "$($artifacts.Replace('\','\\'))"
[Setup]
AppId={{E3B9B1E4-6E56-4C6D-9B6E-REDSIGHTV6}}
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
Write-Host "Compiling with $inno";& $inno /Q /O+ $iss|Out-Host;if($LASTEXITCODE-ne 0){Fail "Inno Setup compilation failed with exit code $LASTEXITCODE"}
$exe=Join-Path $artifacts 'RedSight-Setup-v6.exe';if(-not(Test-Path$exe)){Fail 'Installer EXE was not produced.'}
$hash=(Get-FileHash -Algorithm SHA256 $exe).Hash.ToLowerInvariant();$size=(Get-Item$exe).Length
$manifest=[ordered]@{product='RedSight';distribution='Windows v6';sourceVersion='11.5.5';installerVersion=$AppVersion;builtAt=(Get-Date).ToUniversalTime().ToString('o');architecture='x64';installer='RedSight-Setup-v6.exe';size_bytes=$size;sha256=$hash;wsl='WSL2 enabled/provisioned by resumable bootstrapper';docker='Docker Desktop WSL2 backend provisioned by resumable bootstrapper';offline_bundle=[bool]$BundleOfflineDependencies;notes='Requires supported Windows x64, hardware virtualization, and network access unless offline dependencies were bundled.'}
$manifest|ConvertTo-Json -Depth 8|Set-Content (Join-Path $artifacts 'manifest-v6.json') -Encoding UTF8
"$hash  RedSight-Setup-v6.exe"|Set-Content (Join-Path $artifacts 'SHA256SUMS-v6.txt') -Encoding ASCII
$readme=@"RedSight Windows v6 distribution

Installer: RedSight-Setup-v6.exe
SHA256: $hash
Architecture: Windows x64

The installer enables WSL2, requests a reboot only when required, persists a SYSTEM scheduled task, and resumes automatically after logon. Docker Desktop is configured for the WSL2 backend. The application health gate runs before setup is declared complete.

This build targets supported Windows 10/11 x64 systems. BIOS/UEFI hardware virtualization is mandatory for WSL2. Online mode downloads WSL/Docker components from their official distribution endpoints. Use the build switch -BundleOfflineDependencies for a larger offline-capable bundle.
"@;Set-Content (Join-Path $artifacts 'README.txt') $readme -Encoding UTF8
$zip=Join-Path $OutputRoot 'RedSight-Windows-v6.zip';Compress-Archive -Path (Join-Path $artifacts '*') -DestinationPath $zip -CompressionLevel Optimal -Force
Write-Host "`nBUILD COMPLETE`nInstaller: $exe`nZIP: $zip`nSHA256: $hash`n"
