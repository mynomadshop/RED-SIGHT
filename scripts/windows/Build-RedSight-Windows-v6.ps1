#requires -version 5.1
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
$inno='C:\Program Files\Inno Setup 7\ISCC.exe';if(-not(Test-Path$inno)){$winget=Get-Command winget.exe -ErrorAction SilentlyContinue;if($winget){& winget install --id JRSoftware.InnoSetup.7 -e --silent --accept-source-agreements --accept-package-agreements|Out-Host};if(-not(Test-Path$inno)){Fail 'Inno Setup 7 x64 ISCC.exe is required.'}}
Remove-Item $OutputRoot -Recurse -Force -ErrorAction SilentlyContinue
$stage=Join-Path $OutputRoot 'payload';$offline=Join-Path $stage 'offline';$setupDir=Join-Path $OutputRoot 'installer';$artifacts=Join-Path $OutputRoot 'artifacts';New-Item -ItemType Directory -Force -Path $stage,$setupDir,$artifacts|Out-Null
$excludeDirs=@('.git','.venv','.venv-ui','.venv-actions','data','outputs','dist','__pycache__','tests');$excludeFiles=@('*.pyc','*.pyo','*.log','*.sqlite','*.db')
$robocopyArgs=@($SourceRoot,$stage,'/E','/R:2','/W:1','/NFL','/NDL','/NJH','/NJS','/NP');foreach($d in $excludeDirs){$robocopyArgs+='/XD';$robocopyArgs+=(Join-Path $SourceRoot $d)};foreach($f in $excludeFiles){$robocopyArgs+='/XF';$robocopyArgs+=(Join-Path $SourceRoot $f)};& robocopy.exe @robocopyArgs|Out-Null;if($LASTEXITCODE-gt7){Fail "robocopy failed with exit code $LASTEXITCODE"}
$required=@('pyproject.toml','app\server.py','ui\command_center.py','redsight_actions\gateway.py','scripts\windows\RedSight-Setup-Resume.ps1','scripts\windows\RedSight-PostInstall-Health.ps1','scripts\windows\Start-RedSight.ps1','assets\redsight.ico');foreach($r in $required){if(-not(Test-Path(Join-Path $stage $r))){Fail "Required runtime file missing: $r"}}
# Private Python runtime: CPython NuGet package is the supported lightweight distribution mechanism.
$tools=Join-Path $stage 'tools';New-Item -ItemType Directory -Force -Path $tools|Out-Null;$pyPkg=Join-Path $env:TEMP 'redsight-python-3.12.10.nupkg';Invoke-WebRequest 'https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg' -OutFile $pyPkg -UseBasicParsing;$pyExtract=Join-Path $env:TEMP 'redsight-python-extract';Remove-Item $pyExtract -Recurse -Force -ErrorAction SilentlyContinue;Expand-Archive -LiteralPath $pyPkg -DestinationPath $pyExtract -Force;Copy-Item (Join-Path $pyExtract 'tools\*') $tools -Recurse -Force;Remove-Item $pyPkg,$pyExtract -Recurse -Force -ErrorAction SilentlyContinue
$pyExe=Join-Path $tools 'python.exe';if(-not(Test-Path$pyExe)){Fail 'Bundled Python runtime was not produced.'}
# NuGet CPython contains pip; verify the runtime before compilation.
$pv=& $pyExe --version 2>&1|Out-String;if($pv-notmatch 'Python 3\.12'){Fail "Unexpected bundled Python version: $pv"}
if($BundleOfflineDependencies){New-Item -ItemType Directory -Force -Path $offline|Out-Null;$rel=Invoke-RestMethod 'https://api.github.com/repos/microsoft/WSL/releases/latest' -Headers @{Accept='application/vnd.github+json';'User-Agent'='RedSight-Build'};$a=$rel.assets|Where-Object{$_.name -match '\.x64\.msi$'}|Select-Object -First 1;if(-not$a){Fail 'Could not locate latest Microsoft WSL x64 MSI.'};Invoke-WebRequest $a.browser_download_url -OutFile (Join-Path $offline 'wsl-latest-x64.msi') -UseBasicParsing;if(-not$SkipDockerPayload){Invoke-WebRequest 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe' -OutFile (Join-Path $offline 'Docker-Desktop-Installer-x64.exe') -UseBasicParsing}}
$iss=Join-Path $setupDir 'RedSight-v6.iss';$issText=@"
#define AppName "RedSight"
#define AppVersion "$AppVersion"
#define SourceRoot "$($stage.Replace('\','\\'))"
#define OutputRoot "$($artifacts.Replace('\','\\'))"
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
Set-Content -LiteralPath $iss -Value $issText -Encoding UTF8;& $inno /Q /O+ $iss|Out-Host;if($LASTEXITCODE-ne0){Fail "Inno Setup compilation failed with exit code $LASTEXITCODE"}
$exe=Join-Path $artifacts 'RedSight-Setup-v6.exe';if(-not(Test-Path$exe)){Fail 'Installer EXE was not produced.'};$hash=(Get-FileHash -Algorithm SHA256 $exe).Hash.ToLowerInvariant();$size=(Get-Item$exe).Length
$manifest=[ordered]@{product='RedSight';distribution='Windows v6';sourceVersion='11.5.5';installerVersion=$AppVersion;builtAt=(Get-Date).ToUniversalTime().ToString('o');architecture='x64';installer='RedSight-Setup-v6.exe';size_bytes=$size;sha256=$hash;wsl='WSL2 enabled/provisioned by resumable bootstrapper';docker='Docker Desktop WSL2 backend provisioned by resumable bootstrapper';offline_bundle=[bool]$BundleOfflineDependencies;python='3.12.10 private runtime';notes='Supported Windows x64 only; WSL2 requires hardware virtualization. Online mode downloads Microsoft WSL and Docker Desktop components.'};$manifest|ConvertTo-Json -Depth8|Set-Content(Join-Path $artifacts 'manifest-v6.json')-Encoding UTF8;"$hash  RedSight-Setup-v6.exe"|Set-Content(Join-Path $artifacts 'SHA256SUMS-v6.txt')-Encoding ASCII
$readme="RedSight Windows v6 distribution`r`n`r`nInstaller: RedSight-Setup-v6.exe`r`nSHA256: $hash`r`nArchitecture: Windows x64`r`n`r`nThe installer enables WSL2, restarts only when required, resumes automatically after logon, provisions Docker Desktop for WSL2, and runs a post-install health gate. Online mode downloads current Microsoft WSL and Docker components. Use -BundleOfflineDependencies for a much larger offline-capable build.";Set-Content(Join-Path $artifacts 'README.txt')$readme-Encoding UTF8
$zip=Join-Path $OutputRoot 'RedSight-Windows-v6.zip';Compress-Archive -Path(Join-Path $artifacts '*')-DestinationPath$zip-CompressionLevel Optimal-Force;Write-Host "`nBUILD COMPLETE`nInstaller: $exe`nZIP: $zip`nSHA256: $hash`n"
